import os
import xacro
from launch import LaunchDescription
from launch.substitutions import LaunchConfiguration
from launch.actions import DeclareLaunchArgument
from launch_ros.actions import Node
from ament_index_python import get_package_share_directory

def get_package_file(package, file_path):
    """Get the location of a file installed in an ament package"""
    package_path = get_package_share_directory(package)
    absolute_file_path = os.path.join(package_path, file_path)
    return absolute_file_path

def load_file(file_path):
    """Load the contents of a file into a string"""
    try:
        with open(file_path, 'r') as file:
            return file.read()
    except EnvironmentError: # parent of IOError, OSError *and* WindowsError where available
        return None

def run_xacro(xacro_file):
    """Run xacro and output a file in the same directory with the same name, w/o a .xacro suffix"""
    urdf_file, ext = os.path.splitext(xacro_file)
    if ext != '.xacro':
        raise RuntimeError(f'Input file to xacro must have a .xacro extension, got {xacro_file}')
    os.system(f'xacro {xacro_file} -o {urdf_file}')
    return urdf_file

def generate_launch_description():
    verbose_arg = DeclareLaunchArgument('verbose', default_value=['False'])

    xacro_file = get_package_file('snp_support', 'urdf/workcell.xacro')
    urdf_file = run_xacro(xacro_file)
    srdf_file = get_package_file('snp_support', 'config/workcell.srdf')

    robot_description = load_file(urdf_file)
    robot_description_semantic = load_file(srdf_file)

    # TF information
    planning_server = Node(
        name='snp_planning_server',
        package='snp_motion_planning',
        executable='snp_motion_planning_node',
        output='screen',
        parameters=[{
            'robot_description': robot_description,
            'robot_description_semantic': robot_description_semantic,
            'verbose': LaunchConfiguration('verbose')
        }]
    )

    return LaunchDescription([verbose_arg, planning_server])