#!/usr/bin/env python

# ROS2 boilerplate
import rclpy
import sys
import os
import numpy as np
from rclpy.node import Node
from rclpy.parameter import Parameter

# Roscon
import geometry_msgs.msg
from snp_msgs.srv import GenerateRobotProgram #GenerateRobotProgramResponse, GenerateRobotProgramRequest

sys.path.append(os.path.abspath("/home/larmstrong/catkin_ws/roscon_21/roscon2021/ros2_ws/src/robodk_postprocessors/"))

# Motoman
from Motoman import *
from robodk import *

# Boilerplate
import xml.etree.ElementTree as ET

def pose_to_mat(p):
    """ Converts a quaternion pose p to a matrix representation
    :param p:
    :return:
    """
    # Warning: Quaternion initialization order: w, x, y, z
    quat = [p.orientation.w, p.orientation.x, p.orientation.y, p.orientation.z]
    mat = quaternion_2_pose(quat)
    mat.setPos([p.position.x * 1000., p.position.y * 1000., p.position.z * 1000.])
    return mat


def to_joints(joints):
    """ Converts a list of joint values to controller representation. No joint coupling for joint 2 & 3
    Joint mapping
      ROS joints
        - Ordered according to the kinematic chain: [joint_1, joint_2, joint_3, joint_4, joint_5, joint_6]
        - Units; meters, radians
      Joints on Motoman controller:
        - Order: [joint_1, joint_2, joint_3, joint_4, joint_5, joint_6]
        - Units: degrees

    :param joints:
    :return:
    """
    output_joints = []

    convert = 180.0 / math.pi


    output_joints.append(convert * (joints[0]))
    output_joints.append(convert * (joints[1]))
    output_joints.append(convert * (joints[2]))
    output_joints.append(convert * (joints[3]))
    output_joints.append(convert * (joints[4]))
    output_joints.append(convert * (joints[5]))

    return output_joints


class PostProcessor(Node):
    """ This class hosts action server for program generation
    """
    def __init__(self):
        """ This initialization method initializes the Motoman post processor object, reads the ros parameters,
        and instatiates the action server
        :param self:
        :return:
        """

        super().__init__('ros_to_moto')
        self.srv = self.create_service(GenerateRobotProgram, 'generate_robot_program', self.generate_robot_program)

        # Post processor instance
        self.pp = RobotPost()

        self.declare_parameters(
            namespace='',
            parameters=[('send_prog',True),
                ('robot_ip', '192.168.1.20'),
                ('username', 'user'),
                ('password', 'password'),
                ('zone', '100'),
                ('speed', '200'),
                ('save_dir', 'generated_program')
            ]
        )

        # FTP Programs
        self.send_prog = self.get_parameter('send_prog').get_parameter_value().string_value
        self.robot_ip =  self.get_parameter("robot_ip").get_parameter_value().string_value
        self.username =  self.get_parameter('username').get_parameter_value().string_value
        self.password =  self.get_parameter('password').get_parameter_value().string_value

        # Target program on the teach pendant
        self.master_name = "ROSDEMO"#rospy.get_param("~master_name", None)

        # Motion parameters
        self.zone = self.get_parameter('zone').get_parameter_value().integer_value
        self.speed = self.get_parameter('speed').get_parameter_value().double_value
        #self.joint_speed = self.get_param("joint_speed", Parameter.Type.STRING, '25')

        # Save directory
        self.save_dir = self.get_parameter('save_dir').get_parameter_value().string_value

        #self.Service = self.Service('generate_robot_program', GenerateRobotProgram, self.generate_robot_program)

    # ---------------------High level LS generation -------------------
    def generate_robot_program(self, req, res):
        """ It will return a success bool and sets success or aborted

        :param req: GenerateRobotProgramRequest
        :return:
        """
        print("start")
        # Entries in this list are of form [program name, program comment]
        programNameList = []

        try:
            #Instructions are provided in a list
            for instr in range(0,len(req.instructions)):

                root = ET.fromstring(req.instructions[instr])
                instruction_list = root.find(".//instruction").find(".//container").findall("item")

                # peel first, last instruction
                start_instr = instruction_list[0]
                end_instr = instruction_list[-1]

                # from_start
                programNameList.append([self.createProgramName(len(programNameList)+1),"from_start"])
                print("hello")
                message, success = self.create_inform_from_robot_process_path(start_instr, programNameList[-1][0], programNameList[-1][1])
                if not success:
                    self.get_logger().error("createInformfromRobotProcessPath Failed: %s", message)
                    return [message, success]

                for ind, inst in enumerate(instruction_list[1:-1]):
                    programNameList.append([self.createProgramName(len(programNameList)+1),"process" + str(ind)])
                    message, success = self.create_inform_from_robot_process_path(inst, programNameList[-1][0], programNameList[-1][1])
                    if not success:

                        self.get_logger().error("createInformfromRobotProcessPath Failed: %s", message)
                        return [message, success]

                 To Home
                programNameList.append([self.createProgramName(len(programNameList)+1),"to_end"])
                message, success = self.create_inform_from_robot_process_path(end_instr, programNameList[-1][0], programNameList[-1][1])

                # Create master Inform program
                self.create_master_file("{}".format(self.master_name), programNameList)

                res.success = True

                return res

        except Exception as e:
            res.success = False
            res.error = "Error generating program: {}".format(e)
            return res

    # ------------------------------support functions for generate robot program----------------------
    def createProgramName(self, number):
      """ Creates a file name using provided index 'number'

      :param self:
      :param number:
      :return:
      """
      return "INST_{}".format(number)

    def create_master_file(self, prgname, program_list):
        """  Creates a master LS that will call all other programs generated
        The children programs are stored on the post processor and do not need to be provided

        :param prgname: string - name of master program
        :param program_list: list<string>
        :return:
        """
        self.reset_PROG_vars()

        # -----prog_start-----
        self.pp.ProgStart(prgname)

        # for each point in the trajectory
        for indx, programName in enumerate(program_list):
            # ------run_code-----
            self.pp.RunCode(programName[0], True)

        # ------prog_finish-----
        self.pp.ProgFinish(prgname)

        # ------prog_save-----
        self.pp.ProgSave(self.save_dir, prgname, False, False)

        # ------prog_send_robot-----
        if self.send_prog:
            self.pp.ProgSendRobot(self.robot_ip, "/md:", self.username, self.password)

    def create_inform_from_robot_process_path(self, data, prgname, prgcomment):

        # -----prog_start-----
        self.pp.ProgStart(prgname)

        # ------set_frame-----
        self.pp.setFrame(np.eye(4), 0, "frame")

        smooth_speed = 0.15
        # The following assignment flattens rasters
        waypoints = data.find(".//container").findall(".//waypoint/waypoint")
        for indx in range(0, len(waypoints)):
          wpoint = waypoints[indx]
          # creates a tree with each Waypoint at the root
          pos = [t.text for t in wpoint.find(".//position")[1].findall("item")]
          pos_vec = [float(i) for i in pos]

          if wpoint.find(".//velocity"):
              vel = [t.text for t in wpoint.find(".//velocity")[1].findall("item")]
          else:
              vel = ["0.0"] * 8

          # ------set_speed-----
          self.pp.setSpeed(self.speed)

          # ------set zone------
          self.pp.setZoneData(self.zone)  # This is a % that rounds to corners to maintain velocity.

          move_joints = to_joints(pos_vec)
          self.pp.MoveL(None, move_joints)


        # End of motion instruction loop
        # ------prog_finish-----
        self.pp.ProgFinish(prgname)

        # ------prog_save-----
        self.pp.ProgSave(self.save_dir, prgname, False, False)
        print("4")
        # ------prog_send_robot-----
        if self.send_prog:
            self.pp.ProgSendRobot(self.robot_ip, self.ftp_remote_path, self.username, self.password)

        print("5")
        # Return
        success = True
        message = "Successfully created LS program from robot process path"
        return message, success

    def reset_PROG_vars(self):
        """ Resets the post processor program variables
        :return:
        """
        self.pp.PROG_NAMES = []
        self.pp.PROG_FILES = []
        self.pp.PROG_LIST = []
        self.pp.PROG_CALLS = []
        self.pp.PROG_CALLS_LIST = []
        self.pp.nLines = 0
        self.pp.nProgs = 0
        self.pp.PROG = []  # clears the full PROG structure

    # ---------------------End High level LS generation services --------------

def main(args=None):
    rclpy.init(args=args)
    post_processor= PostProcessor()

    rclpy.spin(post_processor)

    rclpy.shutdown()

if __name__ == '__main__':
    main()
